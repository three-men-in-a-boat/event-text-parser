from flask import Flask, request
import dateparser
import datetime
from dateutil import tz
import re
from dateparser.search import search_dates

app = Flask(__name__)

default_timezone = "UTC"

end_re = re.compile(r"\s+(до|по)\s+", re.IGNORECASE)
start_re = re.compile(r"\s+(начиная с|начиная в|начиная|с|в)\s+", re.IGNORECASE)
prepositions_re = re.compile(r"\s+(начиная с|начиная|с|в|до|по)\s+", re.IGNORECASE)
prepositions_in_end_cleanup_re = re.compile(r"\s+(начиная с|начиная|с|в|на|до|по)$", re.IGNORECASE)

days_re = re.compile(r"(?:^|\s)(позавчера|вчера|сегодня|завтра|послезавтра)(?:\s|$)", re.IGNORECASE)

spaces_re = re.compile(r"\s+")

time_prep_re = re.compile(r"(^|\s)(начиная с|начиная|с|в|на)(\s+\d{1,2}:\d{1,2})", re.IGNORECASE)


def get_text_and_timezone(json_text: dict) -> (str, str):
    timezone_str = str(json_text.get("timezone", default_timezone))
    if timezone_str == "":
        timezone_str = default_timezone

    text = str(json_text.get("text", ""))

    return text, timezone_str


def pre_parse(text: str, timezone_str: str) -> str:
    text = spaces_re.sub(" ", text).strip()

    text = time_prep_re.sub(r"\1 в \3", text)

    text = yesterday_today_tomorrow_transform(text, timezone_str)

    text = spaces_re.sub(" ", text).strip()

    return text


def yesterday_today_tomorrow_transform(text: str, timezone_str: str) -> str:
    # nickeskov: check if we can perform transformation
    if time_prep_re.search(text) is None:
        return text

    day_match = days_re.search(text)
    if day_match is None:
        return text

    # nickeskov: extract day word from regex match
    day_word = day_match.group(0)

    day_datetime = dateparser.parse(day_word, settings={'TIMEZONE': timezone_str})
    if day_datetime is None:
        return text

    text = days_re.sub(r" ", text)
    text = time_prep_re.sub(rf"\1 {day_word} \2\3", text)

    return text


def parse_date(text: str, parsed_tz: datetime.tzinfo) -> dict:
    timezone_str = parsed_tz.tzname(datetime.datetime.now())

    text = pre_parse(text, timezone_str)

    dates = dateparser.search.search_dates(text, settings={'TIMEZONE': timezone_str})
    if dates is None:
        return {}

    # TODO(nickeskov): I know, it's awful...
    if len(dates) > 2:
        month = dates[0][0]
        # сходить до вечера полить огород с 22 марта 14:00 по 22 марта 20:00
        # out: " с 22 марта"
        match_preposition_before_month = re.search(rf"(^|\s)+(до|по|на|с|в)\s+\d+\s+{month}($|\s)+", text,
                                                   re.IGNORECASE)
        # сходить до вечера полить огород 22 марта с 14:00 по 20:00
        # out: "22 марта с"
        match_preposition_after_month = re.search(rf"(^|\s)+\d+\s+{month}\s+(до|по|на|с|в)($|\s)+", text,
                                                  re.IGNORECASE)
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
        dates = dateparser.search.search_dates(text, settings={'TIMEZONE': timezone_str})
        if dates is None:
            return {}

    if len(dates) == 1:
        date_str = dates[0][0]

        updated_date_str = prepositions_re.sub(" в ", date_str)
        dates = dateparser.search.search_dates(updated_date_str, settings={'TIMEZONE': timezone_str})

        event_start_tz = dates[0][1]
        event_name = text.replace(date_str, '').strip()

        event_name = prepositions_in_end_cleanup_re.sub("", event_name)
        event_start_tz = datetime.datetime.combine(event_start_tz.date(), event_start_tz.time(), parsed_tz)

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

        dates = dateparser.search.search_dates(updated_date_str, settings={'TIMEZONE': timezone_str})
        first_date = dates[0]
        second_date = dates[1]

        if end_re.search(updated_date_str) is None:
            return {}

        event_date: datetime.date = first_date[1].date()
        if days_re.search(updated_date_str) is not None:
            event_first_date = first_date[1].date()
            event_second_date = second_date[1].date()
            event_date = max(event_first_date, event_second_date)

        event_start_tz: datetime.datetime = datetime.datetime.combine(
            event_date, first_date[1].time(), parsed_tz
        )
        event_end_tz: datetime.datetime = datetime.datetime.combine(
            event_date, second_date[1].time(), parsed_tz
        )

        if event_end_tz < event_start_tz:
            event_start_tz, event_end_tz = event_end_tz, event_start_tz

        event_name = prepositions_in_end_cleanup_re.sub("", event_name)

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


date_prepositions_re = re.compile(r"(^|\s)+(начиная с|начиная|с|в|до|по)\s+", re.IGNORECASE)
midday_midnight_re = re.compile(r"(^|\s)+пол(удня|удню|день|дня|дню|уночь|уночи|ночью|ночь|ночи|)($|\s)+",
                                re.IGNORECASE)


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

    text = pre_parse(text, timezone_str)
    text = date_prepositions_re.sub(" в ", text)
    text = transform_midday_midnight(text)

    date: datetime.datetime = dateparser.parse(text, settings={"TIMEZONE": timezone_str})
    if date is None:
        return {
            "date": None
        }

    date_with_tz = datetime.datetime.combine(date.date(), date.time(), parsed_tz)

    return {
        "date": date_with_tz.isoformat()
    }


if __name__ == '__main__':
    # res = parse_date("встреча с васенькой завтра в 17:00 до 16:00 ")
    # print(res)
    app.run()
