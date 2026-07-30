package com.streaming.catalog;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.*;
import java.util.stream.Collectors;

@RestController
public class CatalogController {
  @GetMapping("/healthz") public String healthz() { return "ok"; }
  @GetMapping("/readyz")  public String readyz()  { return "ready"; }

  public record Title(String id, String title, String category, String description, String thumbnail, String studio) {}

  private static final String BLENDER_FOUNDATION = "Blender Foundation";

  // Demo catalog, in-memory — real video URLs from the public, Creative-Commons-licensed
  // Blender Foundation open movies. Replace with a PostgreSQL-backed repository for a
  // real production catalog.
  private static final List<Title> TITLES = List.of(
    new Title("1", "Big Buck Bunny", "Comedy",
      "A giant rabbit with a heart bigger than himself gets pushed too far by three rude rodents - and takes hilarious revenge.",
      "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/BigBuckBunny.jpg",
      BLENDER_FOUNDATION),
    new Title("2", "Sintel", "Fantasy",
      "A lonely girl named Sintel searches the world for a baby dragon she raised and lost, in this award-winning independent animated short.",
      "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/Sintel.jpg",
      BLENDER_FOUNDATION),
    new Title("3", "Tears of Steel", "Sci-Fi",
      "In a war-torn future Amsterdam, a group of warriors and scientists gather to stage a crucial event to save the world from destructive robots.",
      "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/TearsOfSteel.jpg",
      BLENDER_FOUNDATION),
    new Title("4", "Elephants Dream", "Fantasy",
      "Two characters explore a strange, surreal machine world in the first ever fully open-source animated short film.",
      "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/ElephantsDream.jpg",
      BLENDER_FOUNDATION)
  );

  @GetMapping("/titles")
  public List<Title> titles(
      @RequestParam(required = false) String category,
      @RequestParam(required = false) String q) {
    return TITLES.stream()
      .filter(t -> category == null || t.category().equalsIgnoreCase(category))
      .filter(t -> q == null || t.title().toLowerCase().contains(q.toLowerCase()))
      .collect(Collectors.toList());
  }

  @GetMapping("/titles/{id}")
  public ResponseEntity<Title> title(@PathVariable String id) {
    return TITLES.stream().filter(t -> t.id().equals(id)).findFirst()
      .map(ResponseEntity::ok)
      .orElse(ResponseEntity.notFound().build());
  }

  @GetMapping("/categories")
  public List<String> categories() {
    return TITLES.stream().map(Title::category).distinct().sorted().collect(Collectors.toList());
  }
}
