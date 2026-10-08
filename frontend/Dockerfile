FROM node:24-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci && cp package-lock.json node_modules/.installed-lock

COPY . .

EXPOSE 5173
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["npm", "run", "dev"]
