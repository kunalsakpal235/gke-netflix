package com.streaming.user;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
public class AuthController {
  @GetMapping("/healthz") public String healthz() { return "ok"; }
  @GetMapping("/readyz")  public String readyz()  { return "ready"; }

  // Demo login — returns a fake token. Replace with Spring Security + real JWT.
  @PostMapping("/login")
  public Map<String,String> login(@RequestBody(required=false) Map<String,String> body) {
    return Map.of("token", "demo-jwt-token", "user", body != null ? body.getOrDefault("user","guest") : "guest");
  }
}
