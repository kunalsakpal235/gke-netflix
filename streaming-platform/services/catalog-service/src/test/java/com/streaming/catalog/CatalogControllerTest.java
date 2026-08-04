package com.streaming.catalog;

import org.junit.jupiter.api.Test;
import com.streaming.catalog.CatalogController.Title;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(CatalogController.class)
class CatalogControllerTest {

  private static final String TITLES_PATH = "/titles";
  private static final String JSON_LENGTH = "$.length()";
  private static final String FANTASY = "Fantasy";

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
  void titlesWithNoFilterReturnsAllFour() throws Exception {
    mockMvc.perform(get(TITLES_PATH))
      .andExpect(status().isOk())
      .andExpect(jsonPath(JSON_LENGTH).value(4));
  }

  @Test
  void titlesFilteredByCategoryReturnsOnlyMatchingOnes() throws Exception {
    mockMvc.perform(get(TITLES_PATH).param("category", FANTASY))
      .andExpect(status().isOk())
      .andExpect(jsonPath(JSON_LENGTH).value(2))
      .andExpect(jsonPath("$[0].category").value(FANTASY))
      .andExpect(jsonPath("$[1].category").value(FANTASY));
  }

  @Test
  void titlesFilteredByCategoryIsCaseInsensitive() throws Exception {
    mockMvc.perform(get(TITLES_PATH).param("category", "comedy"))
      .andExpect(status().isOk())
      .andExpect(jsonPath(JSON_LENGTH).value(1))
      .andExpect(jsonPath("$[0].title").value("Big Buck Bunny"));
  }

  @Test
  void titlesFilteredBySearchQueryMatchesPartialTitle() throws Exception {
    mockMvc.perform(get(TITLES_PATH).param("q", "steel"))
      .andExpect(status().isOk())
      .andExpect(jsonPath(JSON_LENGTH).value(1))
      .andExpect(jsonPath("$[0].title").value("Tears of Steel"));
  }

  @Test
  void titlesFilteredBySearchQueryWithNoMatchReturnsEmptyList() throws Exception {
    mockMvc.perform(get(TITLES_PATH).param("q", "nonexistent-title-xyz"))
      .andExpect(status().isOk())
      .andExpect(jsonPath(JSON_LENGTH).value(0));
  }

  @Test
  void titleByIdReturnsCorrectTitleWhenFound() throws Exception {
    mockMvc.perform(get("/titles/1"))
      .andExpect(status().isOk())
      .andExpect(jsonPath("$.id").value("1"))
      .andExpect(jsonPath("$.title").value("Big Buck Bunny"))
      .andExpect(jsonPath("$.category").value("Comedy"))
      .andExpect(jsonPath("$.studio").value("Blender Foundation"));
  }

  @Test
  void titleByIdReturns404WhenNotFound() throws Exception {
    mockMvc.perform(get("/titles/999"))
      .andExpect(status().isNotFound());
  }

  @Test
  void categoriesReturnsDistinctSortedList() throws Exception {
    mockMvc.perform(get("/categories"))
      .andExpect(status().isOk())
      .andExpect(jsonPath(JSON_LENGTH).value(3))
      .andExpect(jsonPath("$[0]").value("Comedy"))
      .andExpect(jsonPath("$[1]").value(FANTASY))
      .andExpect(jsonPath("$[2]").value("Sci-Fi"));
  }
}
