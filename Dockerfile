FROM registry.k8s.io/git-sync/git-sync:v4.0.0 AS build
FROM python:3.11.0-alpine
COPY --from=build /git-sync /

RUN apk add --no-cache git openssh
RUN pip install --no-cache-dir -U pip

ADD config/ssh_known_hosts /etc/git-secret/known_hosts

WORKDIR /src
RUN mkdir -p directus_git_sync && touch directus_git_sync/__init__.py
ADD pyproject.toml .
RUN pip install --no-cache-dir -e .
ADD directus_git_sync/* directus_git_sync/

ENV GITSYNC_ROOT /git
ENV GITSYNC_EXECHOOK_COMMAND "directus-git-sync-apply"

ENTRYPOINT [ "sh", "-c" ]
CMD [ "/git-sync" ]