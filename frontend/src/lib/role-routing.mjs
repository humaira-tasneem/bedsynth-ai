export function landingPathForRole(role) {
  return role === "admin" ? "/admin" : "/";
}

export function restrictedDestination(role, pathname) {
  if (role === "admin") return null;
  if (pathname === "/admin" || pathname.startsWith("/admin/") || pathname === "/users") return "/";
  return null;
}
