package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strings"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok")) })
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ready")) })

	// Returns a (placeholder) signed HLS manifest URL for a title.
	// In production, sign a Cloud Storage URL via the IAM SignBlob API (keyless, Workload Identity).
	mux.HandleFunc("/play/", func(w http.ResponseWriter, r *http.Request) {
		id := strings.TrimPrefix(r.URL.Path, "/play/")
		bucket := os.Getenv("VIDEO_BUCKET")
		resp := map[string]string{"titleId": id, "manifest": "https://storage.googleapis.com/" + bucket + "/" + id + "/master.m3u8?signed=TODO"}
		json.NewEncoder(w).Encode(resp)
	})

	port := os.Getenv("PORT")
	if port == "" { port = "8080" }
	log.Printf("playback-service on :%s", port)
	log.Fatal(http.ListenAndServe(":"+port, mux))
}
