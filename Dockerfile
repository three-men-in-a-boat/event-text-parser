FROM tiangolo/uwsgi-nginx-flask:python3.8
ARG APP=/app
WORKDIR ${APP}

COPY requirements.txt ${APP}/requirements.txt
RUN pip3 install -r ${APP}/requirements.txt

COPY . ${APP}
# nickeskov: replace default uwsgi.ini file
COPY uwsgi.ini ${APP}/uwsgi.ini
