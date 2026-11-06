# Local development only (docker compose). Production builds run on Vercel.
FROM node:24.22.2-slim

ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
RUN chown node:node /app
USER node

COPY --chown=node:node package.json package-lock.json ./
RUN npm ci

COPY --chown=node:node . .
# Created here so the compose volume for .next is owned by `node`, not root.
RUN mkdir -p .next

EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
