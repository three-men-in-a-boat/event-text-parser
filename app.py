from flask import Flask, request
import dateparser
import datetime
from dateutil import tz
import re
from dateparser.search import search_dates

app = Flask(__name__)

default_timezone = "UTC"

pre_re = re.compile(r"\s+(начиная с|начиная в|начиная)\s+")
pre_check_re = re.compile(r"^\s*(начиная с|начиная в|начиная|с|в|по|до)\s+\d+")
pre_begin_re = re.compile(r"^\s*(начиная с|начиная в|начиная|с|в|по|до)\s+")

end_re = re.compile(r"\s+(до|по)\s+")
start_re = re.compile(r"\s+(начиная с|начиная в|начиная|с|в)\s+")
prepositions_re = re.compile(r"\s+(начиная с|начиная|с|в|до|по)\s+")
prepositions_in_end_cleanup_re = re.compile(r"\s+(начиная с|начиная|с|в|на|до|по)$")

days_re = re.compile(r"\s+(позавчера|вчера|сегодня|завтра|послезавтра)\s+")

spaces_re = re.compile(r"\s+")


def get_text_and_timezone(json_text: dict) -> (str, str):
    timezone_str = str(json_text.get("timezone", "UTC"))
    if timezone_str == "":
        timezone_str = default_timezone

    text = str(json_text.get("text", ""))

    return text, timezone_str


def pre_parse(text: str) -> str:
    text = spaces_re.sub(" ", text).strip()
    text = pre_re.sub(" в ", text)

    matches = pre_check_re.search(text)
    if matches is not None:
        text = pre_begin_re.sub(" в ", text, 1)

    return text


def parse_date(text: str, parsed_tz: datetime.tzinfo) -> dict:
    text = pre_parse(text)

    dates = dateparser.search.search_dates(text)
    if dates is None:
        return {}

    # TODO(nickeskov): I know, it's awful...
    if len(dates) > 2:
        month = dates[0][0]
        # сходить до вечера полить огород с 22 марта 14:00 по 22 марта 20:00
        # out: " с 22 марта"
        match_preposition_before_month = re.search(rf"(^|\s)+(до|по|на|с|в)\s+\d+\s+{month}($|\s)+", text)
        # сходить до вечера полить огород 22 марта с 14:00 по 20:00
        # out: "22 марта с"
        match_preposition_after_month = re.search(rf"(^|\s)+\d+\s+{month}\s+(до|по|на|с|в)($|\s)+", text)
        if match_preposition_before_month is None and match_preposition_after_month is None:
            return {}

        if match_preposition_before_month is not None:
            datemonth_string = match_preposition_before_month.group()
            replace_str = f" {' '.join(datemonth_string.split()[1:])} "
            text = text.replace(datemonth_string, replace_str, 1)

        if match_preposition_after_month is not None:
            datemonth_string = match_preposition_after_month.group()
            split = datemonth_string.split()
            replace_str = f" {' '.join(split[:len(split) - 1])} "
            text = text.replace(datemonth_string, replace_str, 1)

        text = spaces_re.sub(" ", text).strip()
        dates = dateparser.search.search_dates(text)
        if dates is None:
            return {}

    if len(dates) == 1:
        date_str = dates[0][0]

        updated_date_str = prepositions_re.sub(" в ", date_str)
        dates = dateparser.search.search_dates(updated_date_str)

        event_start = dates[0][1]
        event_name = text.replace(date_str, '').strip()

        event_name = prepositions_in_end_cleanup_re.sub("", event_name)
        event_start_tz = event_start.astimezone(parsed_tz)

        return {
            "event_name": event_name,
            "event_start": event_start_tz.isoformat(),
            "event_end": None,
        }

    if len(dates) == 2:
        first_date = dates[0]
        second_date = dates[1]

        substr = text[text.find(first_date[0]):]
        date_str = substr[:text.find(second_date[0]) + len(second_date[0])]

        event_name = text.replace(date_str, '').strip()

        updated_date_str = start_re.sub(" в ", date_str)

        dates = dateparser.search.search_dates(updated_date_str)
        first_date = dates[0]
        second_date = dates[1]

        if end_re.search(updated_date_str) is None:
            return {}

        event_date: datetime.date = first_date[1].date()
        if days_re.search(updated_date_str) is not None:
            event_first_date = first_date[1].date()
            event_second_date = second_date[1].date()
            event_date = max(event_first_date, event_second_date)

        event_start: datetime.datetime = datetime.datetime.combine(event_date, first_date[1].time())
        event_end: datetime.datetime = datetime.datetime.combine(event_date, second_date[1].time())

        if event_end < event_start:
            event_start, event_end = event_end, event_start

        event_name = prepositions_in_end_cleanup_re.sub("", event_name)

        event_start_tz = event_start.astimezone(parsed_tz)
        event_end_tz = event_end.astimezone(parsed_tz)

        return {
            "event_name": event_name,
            "event_start": event_start_tz.isoformat(),
            "event_end": event_end_tz.isoformat(),
        }

    return {}


@app.route('/api/v1/parse/event', methods=['PUT'])
def parse_event_text():
    json_text = request.json

    text, timezone_str = get_text_and_timezone(json_text)

    parsed_tz: datetime.tzinfo = tz.gettz(timezone_str)
    if parsed_tz is None:
        return {
                   "error": "invalid_timezone",
                   "error_description": f"invalid timezone '{timezone_str}'"
               }, 400

    datejson = {}
    try:
        datejson = parse_date(text, parsed_tz)
    except Exception as e:
        app.logger.error(e)

    return datejson


date_prepositions_re = re.compile(r"(^|\s)+(начиная с|начиная|с|в|до|по)\s+")
midday_midnight_re = re.compile(r"(^|\s)+пол(удня|удню|день|дня|дню|уночь|уночи|ночью|ночь|ночи|)($|\s)+")


def transform_midday_midnight(text: str) -> str:
    res = midday_midnight_re.search(text)
    if res is None:
        return text
    word = res.group().strip()
    if "дн" in word or "ден" in word:
        text = midday_midnight_re.sub(" 12:00 ", text)
    elif "ноч" in word:
        text = midday_midnight_re.sub(" 00:00 ", text)

    return text.strip()


@app.route('/api/v1/parse/date', methods=['PUT'])
def parse_date_from_text():
    json_text = request.json

    text, timezone_str = get_text_and_timezone(json_text)

    parsed_tz: datetime.tzinfo = tz.gettz(timezone_str)
    if parsed_tz is None:
        return {
                   "error": "invalid_timezone",
                   "error_description": f"invalid timezone '{timezone_str}'"
               }, 400

    text = pre_parse(text)
    text = date_prepositions_re.sub(" в ", text)
    text = transform_midday_midnight(text)

    date: datetime.datetime = dateparser.parse(text)
    if date is None:
        return {
            "date": None
        }

    date_with_tz = date.astimezone(parsed_tz)

    return {
        "date": date_with_tz.isoformat()
    }


if __name__ == '__main__':
    # res = parse_date("встреча с васенькой завтра в 17:00 до 16:00 ")
    # print(res)
    app.run()
