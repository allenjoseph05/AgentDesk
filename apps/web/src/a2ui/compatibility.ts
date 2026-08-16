/**
 * Compile-time guard for the A2UI 0.9.1 renderer family selected in ADR 0001.
 *
 * Importing from unversioned entrypoints selects legacy v0.8 behavior in the
 * current packages, so protocol-facing code must import through this boundary.
 */
export { A2uiSurface, basicCatalog } from "@a2ui/react/v0_9";
export { MessageProcessor } from "@a2ui/web_core/v0_9";

export const A2UI_PROTOCOL_VERSION = "v0.9.1" as const;

