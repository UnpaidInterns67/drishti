// Vercel project root: web. Set BACKEND_ORIGIN to the deployed Render HTTPS URL.
const origin = new URL(process.env.BACKEND_ORIGIN || "https://configure-backend.invalid");
if (origin.protocol !== "https:" || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !origin.hostname.endsWith(".onrender.com")) {
  throw new Error("BACKEND_ORIGIN must be the Render service HTTPS origin, without a path or credentials");
}

export default {
  framework: null,
  buildCommand: "node build.mjs",
  outputDirectory: "dist",
  rewrites: [
    { source: "/api/:path*", destination: `${origin.origin}/api/:path*` },
    { source: "/health", destination: `${origin.origin}/health` },
  ],
  headers: [{
    source: "/(.*)",
    headers: [
      { key: "Cache-Control", value: "no-store" },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "no-referrer" },
      { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
      { key: "Content-Security-Policy", value: "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'" },
    ],
  }],
};
