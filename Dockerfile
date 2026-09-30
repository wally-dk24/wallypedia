# wallypedia — local-first static wiki over markdown notes
#
# Build:  docker build -t wallydk24/wallypedia .
# Build your wiki:
#   docker run --rm -v ~/notes:/notes -v ~/site:/site wallydk24/wallypedia \
#     build --notes /notes --out /site
# Then open ~/site/index.html in a browser. Stdlib only — no dependencies.

FROM python:3.12-alpine

WORKDIR /app
COPY wallypedia.py ./
RUN adduser -D wiki && chown -R wiki:wiki /app
USER wiki

VOLUME ["/notes", "/site"]
ENTRYPOINT ["python3", "/app/wallypedia.py"]
CMD ["--help"]
