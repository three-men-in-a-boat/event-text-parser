from flask import Flask, request
import dateparser
import datetime
import re
from dateparser.search import search_dates

app = Flask(__name__)


pre_re = re.compile(r"\s+(начиная с|начиная в|начиная)\s+")
pre_check_re = re.compile(r"^\s*(начиная с|начиная в|начиная|с|в|по|до)\s+\d+")
pre_begin_re = re.compile(r"^\s*(начиная с|начиная в|начиная|с|в|по|до)\s+")

end_re = re.compile(r"\s+(до|по)\s+")
start_re = re.compile(r"\s+(начиная с|начиная в|начиная|с|в)\s+")
prepositions_re = re.compile(r"\s+(начиная с|начиная|с|в|до|по)\s+")

days_re = re.compile(r"\s+(позавчера|вчера|сегодня|завтра|послезавтра)\s+")

spaces_re = re.compile(r"\s+")


def parse_date(text: str):
    text = spaces_re.sub(" ", text).strip()
    text = pre_re.sub(" в ", text)

    kek = pre_check_re.findall(text)

    if len(kek) != 0:
        text = pre_begin_re.sub(" в ", text, 1)

    dates = dateparser.search.search_dates(text)
    if dates is None:
        return {}

    if len(dates) == 1:
        date_str = dates[0][0]

        updated_date_str = prepositions_re.sub(" в ", date_str)
        dates = dateparser.search.search_dates(updated_date_str)

        event_start = dates[0][1]
        event_name = text.replace(date_str, '').strip()

        return {
            "event_name": event_name,
            "event_start": event_start.isoformat(),
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

        if len(end_re.findall(updated_date_str)) == 0:
            return {}

        event_date: datetime.date = first_date[1].date()
        if len(days_re.findall(updated_date_str)) != 0:
            event_first_date = first_date[1].date()
            event_second_date = second_date[1].date()
            event_date = max(event_first_date, event_second_date)

        event_start: datetime.datetime = datetime.datetime.combine(event_date, first_date[1].time())
        event_end: datetime.datetime = datetime.datetime.combine(event_date, second_date[1].time())

        if event_end < event_start:
            event_start, event_end = event_end, event_start

        return {
            "event_name": event_name,
            "event_start": event_start.isoformat(),
            "event_end": event_end.isoformat(),
        }

    return {}


@app.route('/api/v1/parse-event', methods=['GET'])
def parse_event_text():
    json_text = request.json
    text = str(json_text["text"])
    datejson = {}
    try:
        datejson = parse_date(text)
    except Exception as e:
        app.logger.error(e)

    return datejson


if __name__ == '__main__':
    pass
    # res = parse_date("встреча с васенькой завтра в 17:00 до 16:00 ")
    # print(res)
    app.run()
