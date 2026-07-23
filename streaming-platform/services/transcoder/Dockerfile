FROM node:20-alpine
RUN apk add --no-cache ffmpeg
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY . .
USER node
CMD ["node","worker.js"]
