export function landingPathForRole(role) {
  return role === "admin" ? "/hospitals" : "/";
}

export function restrictedDestination(role, pathname) {
  const retiredRoutes = pathname === "/admin" || pathname.startsWith("/admin/")
    || pathname === "/users" || pathname.startsWith("/users/")
    || pathname === "/assistant" || pathname.startsWith("/assistant/")
    || pathname === "/guest" || pathname.startsWith("/guest/");
  if (role === "admin") {
    return retiredRoutes || pathname === "/validation" || pathname.startsWith("/validation/")
      ? "/hospitals"
      : null;
  }
  if (retiredRoutes) return "/";
  if (pathname === "/hospitals" || pathname.startsWith("/hospitals/")) return "/generate";
  return null;
}
