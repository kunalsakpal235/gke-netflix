output "name" {
  value = one(concat(google_container_cluster.autopilot[*].name, google_container_cluster.standard[*].name))
}
output "location" {
  value = one(concat(google_container_cluster.autopilot[*].location, google_container_cluster.standard[*].location))
}
