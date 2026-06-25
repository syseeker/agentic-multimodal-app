# SvelteKit UI (adapter-node). Multi-arch: node base builds on amd64 + arm64.
FROM node:20-slim AS build
WORKDIR /ui
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM node:20-slim
WORKDIR /ui
COPY --from=build /ui/build ./build
COPY --from=build /ui/package.json ./
COPY --from=build /ui/node_modules ./node_modules
ENV PORT=5173
EXPOSE 5173
CMD ["node", "build"]
