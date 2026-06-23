// Runtime API endpoint override. Edit this file (or replace at deploy time)
// without rebuilding the Astro bundle.
//
// Examples:
//   window.__API_BASE__ = "http://192.168.1.42:8000";   // same LAN as host
//   window.__API_BASE__ = "https://api.researchpapers.example.com";
//
// If unset, build-time PUBLIC_API_URL wins. Public Pages deployments then use
// bundled static JSON for search and same-origin Pages Functions for RAG.
window.__API_BASE__ = undefined;
