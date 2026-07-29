package com.streaming.catalog;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.*;
import java.util.stream.Collectors;

@RestController
public class CatalogController {
  @GetMapping("/healthz") public String healthz() { return "ok"; }
  @GetMapping("/readyz")  public String readyz()  { return "ready"; }

  // Demo catalog, in-memory — real video URLs from the public, Creative-Commons-licensed
  // Blender Foundation open movies. Replace with a PostgreSQL-backed repository for a
  // real production catalog.
  private static final List<Map<String,String>> TITLES = List.of(
    Map.of("id","1","title","Big Buck Bunny","category","Comedy",
      "description","A giant rabbit with a heart bigger than himself gets pushed too far by three rude rodents - and takes hilarious revenge.",
      "thumbnail","https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/BigBuckBunny.jpg",
      "studio","Blender Foundation"),
    Map.of("id","2","title","Sintel","category","Fantasy",
      "description","A lonely girl named Sintel searches the world for a baby dragon she raised and lost, in this award-winning independent animated short.",
      "thumbnail","https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/Sintel.jpg",
      "studio","Blender Foundation"),
    Map.of("id","3","title","Tears of Steel","category","Sci-Fi",
      "description","In a war-torn future Amsterdam, a group of warriors and scientists gather to stage a crucial event to save the world from destructive robots.",
      "thumbnail","https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/TearsOfSteel.jpg",
      "studio","Blender Foundation"),
    Map.of("id","4","title","Elephants Dream","category","Fantasy",
      "description","Two characters explore a strange, surreal machine world in the first ever fully open-source animated short film.",
      "thumbnail","https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/ElephantsDream.jpg",
      "studio","Blender Foundation")
  );

  @GetMapping("/titles")
  public List<Map<String,String>> titles(
      @RequestParam(required = false) String category,
      @RequestParam(required = false) String q) {
    return TITLES.stream()
      .filter(t -> category == null || t.get("category").equalsIgnoreCase(category))
      .filter(t -> q == null || t.get("title").toLowerCase().contains(q.toLowerCase()))
      .collect(Collectors.toList());
  }

  @GetMapping("/titles/{id}")
  public ResponseEntity<Map<String,String>> title(@PathVariable String id) {
    return TITLES.stream().filter(t -> t.get("id").equals(id)).findFirst()
      .map(ResponseEntity::ok)
      .orElse(ResponseEntity.notFound().build());
  }

  @GetMapping("/categories")
  public List<String> categories() {
    return TITLES.stream().map(t -> t.get("category")).distinct().sorted().collect(Collectors.toList());
  }
}
