FROM node:20-alpine

WORKDIR /app

# Install Docker CLI (needed to manage demo instances)
RUN apk add --no-cache docker-cli docker-compose curl

COPY package*.json ./
RUN npm ci --production

COPY . .

EXPOSE 3311

CMD ["node", "server.js"]
