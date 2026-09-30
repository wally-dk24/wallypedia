# wallypedia — local-first static wiki over markdown notes
# (multi-arch: linux/amd64, linux/arm64 — e.g. Raspberry Pi)
#
# Build:  podman build --platform linux/arm64 -t wallydk24/wallypedia:arm64 .
# Build your wiki (one-shot static site):
#   docker run --rm -v ~/notes:/notes -v ~/site:/site wallydk24/wallypedia \
#     build --notes /notes --out /site
# Then open ~/site/index.html in a browser.
#
# Or serve it with a browser UI for uploading new notes:
#   docker run -d -p 8080:8080 -v ~/notes:/notes wallydk24/wallypedia \
#     serve --notes /notes --port 8080
# Then open http://localhost:8080 (upload at /upload). Uploaded .md files
# land in ~/notes and the wiki rebuilds itself. Stdlib only — no dependencies.

FROM python:3.12-alpine

WORKDIR /app
COPY wallypedia.py ./
USER 1000

EXPOSE 8080
VOLUME ["/notes", "/site"]
ENTRYPOINT ["python3", "/app/wallypedia.py"]
CMD ["--help"]
