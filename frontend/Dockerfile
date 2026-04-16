FROM node:20-alpine AS base
RUN npm install -g pnpm@9
WORKDIR /app
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

FROM base AS dev
COPY . .
EXPOSE 5173
CMD ["pnpm", "dev", "--host"]

FROM base AS production
COPY . .
RUN pnpm build
FROM nginx:alpine AS production-serve
COPY --from=production /app/dist /usr/share/nginx/html
EXPOSE 80
