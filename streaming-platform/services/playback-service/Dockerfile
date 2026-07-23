FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /playback ./cmd/server
FROM gcr.io/distroless/static-debian12
COPY --from=build /playback /playback
USER nonroot:nonroot
EXPOSE 8093
ENTRYPOINT ["/playback"]
