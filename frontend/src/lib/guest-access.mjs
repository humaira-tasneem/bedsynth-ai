export function guestApiPrefix(isGuest) {
  return isGuest ? "/api/v1/guest" : "/api/v1";
}

export function guestDatasetPath(runId) {
  return `/guest/datasets/${encodeURIComponent(runId)}`;
}

export function guestRouteAllowed(pathname) {
  return pathname === "/" || pathname === "/generate" || pathname === "/login" || pathname === "/register"
    || /^\/guest\/datasets\/[^/]+$/.test(pathname);
}
