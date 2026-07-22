FROM gradle:8.9-jdk21-alpine AS build
WORKDIR /src
COPY . .
RUN gradle clean bootJar --no-daemon
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
RUN addgroup -g 1000 -S app && adduser -u 1000 -S app -G app
COPY --from=build --chown=app:app /src/build/libs/*.jar app.jar
USER app
EXPOSE 8080
ENV JAVA_OPTS="-XX:MaxRAMPercentage=75"
ENTRYPOINT ["sh","-c","java $JAVA_OPTS -jar app.jar"]
