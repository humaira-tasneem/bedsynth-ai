export function landingPathForRole(role: "admin" | "user"): string;
export function restrictedDestination(role: "admin" | "user", pathname: string): string | null;
