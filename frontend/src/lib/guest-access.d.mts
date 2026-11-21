export function guestApiPrefix(isGuest: boolean): "/api/v1/guest" | "/api/v1";
export function guestDatasetPath(runId: string): string;
export function guestRouteAllowed(pathname: string): boolean;
