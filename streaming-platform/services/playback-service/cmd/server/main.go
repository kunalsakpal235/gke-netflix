package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strings"
)

// Real, working, Creative-Commons-licensed video URLs (Blender Foundation open movies,
// hosted on Google's public sample bucket). This replaces the earlier HLS-manifest
// placeholder (which pointed at "signed=TODO" and never played anything real) with
// direct MP4 URLs that any browser's <video> tag plays natively - no extra JS libraries
// needed. For a real production service, this would sign private Cloud Storage URLs via
// the IAM SignBlob API (keyless, Workload Identity) instead.
var videoURLs = map[string]string{
	"1": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
	"2": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/Sintel.mp4",
	"3": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4",
	"4": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4",
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok")) })
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ready")) })

	mux.HandleFunc("/play/", func(w http.ResponseWriter, r *http.Request) {
		id := strings.TrimPrefix(r.URL.Path, "/play/")
		url, ok := videoURLs[id]
		w.Header().Set("Content-Type", "application/json")
		if !ok {
			w.WriteHeader(http.StatusNotFound)
			json.NewEncoder(w).Encode(map[string]string{"error": "no video for titleId " + id})
			return
		}
		json.NewEncoder(w).Encode(map[string]string{"titleId": id, "videoUrl": url})
	})

	port := os.Getenv("PORT")
	if port == "" {
		port = "8093"
	}
	log.Printf("playback-service on :%s", port)
	log.Fatal(http.ListenAndServe(":"+port, mux))
}
