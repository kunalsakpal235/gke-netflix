package com.streaming.catalog;
import org.springframework.web.bind.annotation.*;
import java.util.List;
import java.util.Map;

@RestController
public class CatalogController {
  @GetMapping("/healthz") public String healthz() { return "ok"; }
  @GetMapping("/readyz")  public String readyz()  { return "ready"; }

  // Demo catalog — replace with a PostgreSQL-backed repository.
  @GetMapping("/titles")
  public List<Map<String,String>> titles() {
    return List.of(
      Map.of("id","1","name","Big Buck Bunny"),
      Map.of("id","2","name","Sintel"),
      Map.of("id","3","name","Tears of Steel"));
  }
}
