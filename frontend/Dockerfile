FROM node:20-slim AS deps

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-slim AS builder

WORKDIR /app

ARG INTERNAL_API_BASE=http://backend:8000
ARG NEXT_PUBLIC_API_BASE=

ENV INTERNAL_API_BASE=${INTERNAL_API_BASE}
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
ENV NODE_ENV=production

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

FROM node:20-slim AS runner

WORKDIR /app

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000

ARG INTERNAL_API_BASE=http://backend:8000
ARG NEXT_PUBLIC_API_BASE=

ENV INTERNAL_API_BASE=${INTERNAL_API_BASE}
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
