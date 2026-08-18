FROM node:20-alpine AS build

WORKDIR /app
COPY package.json yarn.lock* yarn.lock.prod* ./
RUN if [ ! -f yarn.lock ] && [ -f yarn.lock.prod ]; then mv yarn.lock.prod yarn.lock; fi \
    && yarn install --frozen-lockfile --network-timeout 300000

COPY . .

ARG REACT_APP_BACKEND_URL
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL \
    GENERATE_SOURCEMAP=false \
    NODE_OPTIONS=--max-old-space-size=2048

RUN yarn build

FROM nginx:1.27-alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
