package com.streaming.user;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(UserController.class)
class UserControllerTest {

  private static final String LOGIN_PATH = "/login";
  private static final String VIEWER = "viewer";

  @Autowired
  private MockMvc mockMvc;

  @Test
  void healthzReturnsOk() throws Exception {
    mockMvc.perform(get("/healthz"))
      .andExpect(status().isOk())
      .andExpect(content().string("ok"));
  }

  @Test
  void readyzReturnsReady() throws Exception {
    mockMvc.perform(get("/readyz"))
      .andExpect(status().isOk())
      .andExpect(content().string("ready"));
  }

  @Test
  void loginReturnsTokenAndUserWhenUsernameProvided() throws Exception {
    mockMvc.perform(post(LOGIN_PATH)
        .contentType(MediaType.APPLICATION_JSON)
        .content("{\"user\":\"alice\"}"))
      .andExpect(status().isOk())
      .andExpect(jsonPath("$.token").value(org.hamcrest.Matchers.startsWith("demo-")))
      .andExpect(jsonPath("$.user").value("alice"))
      .andExpect(jsonPath("$.roles[0]").value(VIEWER));
  }

  @Test
  void loginFallsBackToAnonymousWhenNoUserProvided() throws Exception {
    mockMvc.perform(post(LOGIN_PATH)
        .contentType(MediaType.APPLICATION_JSON)
        .content("{}"))
      .andExpect(status().isOk())
      .andExpect(jsonPath("$.user").value("anonymous"))
      .andExpect(jsonPath("$.roles[0]").value(VIEWER));
  }

  @Test
  void loginGeneratesUniqueTokenPerRequest() throws Exception {
    // Two consecutive logins should produce two different UUIDs - proves the UUID call
    // isn't cached or constant across requests.
    var result1 = mockMvc.perform(post(LOGIN_PATH)
        .contentType(MediaType.APPLICATION_JSON)
        .content("{\"user\":\"bob\"}"))
      .andReturn().getResponse().getContentAsString();
    var result2 = mockMvc.perform(post(LOGIN_PATH)
        .contentType(MediaType.APPLICATION_JSON)
        .content("{\"user\":\"bob\"}"))
      .andReturn().getResponse().getContentAsString();
    org.junit.jupiter.api.Assertions.assertNotEquals(result1, result2);
  }
}
