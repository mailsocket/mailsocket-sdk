FROM python:3.12-slim
RUN pip install --no-cache-dir mailsocket-mcp==0.1.1
ENV MAILSOCKET_API_KEY=ms_live_placeholder_for_introspection
CMD ["mailsocket-mcp"]
