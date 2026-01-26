# Dockerfile for Wi-Lab Angular Frontend Build
# This image compiles the Angular frontend to a minified production bundle.
# Build artifacts are copied to /build-output/wi-lab-frontend inside the image.

FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build minified production bundle and stage output
RUN npm run build:prod \
	&& mkdir -p /build-output \
	&& cp -r dist/wi-lab-frontend /build-output/

# Default: show build completion
CMD ["sh", "-c", "echo '✅ Frontend build complete!' && echo 'Output staged at /build-output/wi-lab-frontend' && ls -lah /build-output/wi-lab-frontend"]
