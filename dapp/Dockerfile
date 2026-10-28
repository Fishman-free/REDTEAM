FROM node:22-bookworm-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

ARG VITE_API_URL=/api
ARG VITE_RPC_URL=/rpc
ARG VITE_EXPLORER_URL=
ENV VITE_API_URL=$VITE_API_URL \
    VITE_RPC_URL=$VITE_RPC_URL \
    VITE_EXPLORER_URL=$VITE_EXPLORER_URL

RUN npm run build

FROM node:22-bookworm-slim AS runtime

WORKDIR /app
ENV NODE_ENV=production

COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

COPY server.mjs ./
COPY --from=build /app/dist ./dist

EXPOSE 3000

CMD ["node", "server.mjs"]
