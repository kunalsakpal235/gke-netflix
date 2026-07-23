FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY . .
FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=8080
COPY --from=build /app ./
USER node
EXPOSE 8080
CMD ["node","server.js"]
