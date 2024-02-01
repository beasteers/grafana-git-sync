FROM registry.k8s.io/git-sync/git-sync:v4.0.0 AS build
FROM python:3.11.0-alpine
COPY --from=build /git-sync /

RUN apk add --no-cache git openssh
RUN pip install --no-cache-dir -U pip

ADD config/ssh_known_hosts /etc/git-secret/known_hosts

WORKDIR /src
RUN mkdir -p grafana_git_sync && touch grafana_git_sync/__init__.py
ADD pyproject.toml .
RUN pip install --no-cache-dir -e .
ADD grafana_git_sync/* grafana_git_sync/

ENV GITSYNC_ROOT /git
ENV GITSYNC_EXECHOOK_COMMAND "grafana-git-sync-apply"

ENTRYPOINT [ "sh", "-c" ]
CMD [ "/git-sync" ]