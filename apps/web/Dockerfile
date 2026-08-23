# syntax=docker/dockerfile:1

ARG NODE_VERSION=24.17.0
FROM node:${NODE_VERSION}-bookworm-slim AS development

ENV NODE_ENV=development

WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json

RUN npm ci --workspaces --include-workspace-root

COPY --chown=node:node apps/web ./apps/web

RUN chown -R node:node /app/apps/web

USER node
WORKDIR /app/apps/web

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
