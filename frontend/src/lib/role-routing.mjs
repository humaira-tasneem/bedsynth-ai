export function landingPathForRole(role) {
  return role === "admin" ? "/hospitals" : "/";
}

export function restrictedDestination(role, pathname) {
  const retiredAdminRoutes = pathname === "/admin" || pathname.startsWith("/admin/")
    || pathname === "/users" || pathname.startsWith("/users/")
    || pathname === "/assistant" || pathname.startsWith("/assistant/")
    || pathname === "/guest" || pathname.startsWith("/guest/");
  if (role === "admin") {
    return retiredAdminRoutes || pathname === "/analytics" || pathname.startsWith("/analytics/")
      || pathname === "/validation" || pathname.startsWith("/validation/")
      ? "/hospitals"
      : null;
  }
  if (retiredAdminRoutes) return "/";
  if (pathname === "/hospitals" || pathname.startsWith("/hospitals/")) return "/generate";
  return null;
}
