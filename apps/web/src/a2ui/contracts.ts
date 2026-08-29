import { z } from "zod";

export const A2UI_SURFACE_EVENT_NAME = "agentdesk.a2ui.surface.v1" as const;
export const A2UI_CATALOG_ID = "agentdesk.dev:intake-v1" as const;
export const A2UI_SUBMIT_ACTION = "agentdesk.intake.submit.v1" as const;
export const A2UI_SKIP_ACTION = "agentdesk.intake.skip.v1" as const;
export const MAX_A2UI_SURFACE_BYTES = 128 * 1024;

const text = z.string().trim().min(1).max(16 * 1024);
const identifier = z.string().trim().min(1).max(255);
const fieldIdentifier = z.string().regex(/^[a-z][a-z0-9_-]{0,127}$/);
const plainText = text.refine(
  (value) =>
    !/<\s*\/?\s*[a-z][^>]*>/i.test(value) &&
    !/(?:https?|javascript|data):|\{\{|\$\{/i.test(value) &&
    !Array.from(value).some((character) => {
      const code = character.charCodeAt(0);
      return code < 32 && character !== "\t" && character !== "\n" && character !== "\r";
    }),
  "A2UI display text must be inert plain text.",
);
const accessibility = z
  .object({ label: plainText.optional(), description: plainText.optional() })
  .strict();
const binding = z.object({ path: z.string().regex(/^\/answers\/(?:[^~/]|~[01])+$/) }).strict();
const childList = z.array(identifier).max(32);

const identityContext = {
  sessionId: identifier,
  proposalId: identifier,
  proposalVersion: z.literal("1.0"),
};
const submitEvent = z
  .object({
    name: z.literal(A2UI_SUBMIT_ACTION),
    context: z.object({ ...identityContext, answers: z.object({ path: z.literal("/answers") }).strict() }).strict(),
  })
  .strict();
const skipEvent = z
  .object({ name: z.literal(A2UI_SKIP_ACTION), context: z.object(identityContext).strict() })
  .strict();
const buttonAction = z.object({ event: z.union([submitEvent, skipEvent]) }).strict();

const textComponent = z
  .object({
    id: identifier,
    component: z.literal("Text"),
    text: plainText,
    variant: z.enum(["h2", "caption", "body"]),
  })
  .strict();
const textFieldComponent = z
  .object({
    id: identifier,
    component: z.literal("TextField"),
    label: plainText,
    value: binding,
    variant: z.literal("shortText"),
    accessibility,
  })
  .strict();
const choicePickerComponent = z
  .object({
    id: identifier,
    component: z.literal("ChoicePicker"),
    label: plainText,
    variant: z.enum(["mutuallyExclusive", "multipleSelection"]),
    options: z
      .array(z.object({ label: plainText, value: plainText }).strict())
      .min(1)
      .max(8),
    value: binding,
    displayStyle: z.literal("checkbox"),
    filterable: z.literal(false),
    accessibility,
  })
  .strict();
const checkBoxComponent = z
  .object({
    id: identifier,
    component: z.literal("CheckBox"),
    label: plainText,
    value: binding,
    accessibility,
  })
  .strict();
const columnComponent = z
  .object({
    id: identifier,
    component: z.literal("Column"),
    children: childList,
    justify: z.literal("start"),
    align: z.literal("stretch"),
  })
  .strict();
const rowComponent = z
  .object({
    id: identifier,
    component: z.literal("Row"),
    children: childList,
    justify: z.literal("start"),
    align: z.literal("center"),
  })
  .strict();
const buttonComponent = z
  .object({
    id: identifier,
    component: z.literal("Button"),
    child: identifier,
    variant: z.enum(["primary", "borderless"]),
    accessibility,
    action: buttonAction,
  })
  .strict();

export const IntakeComponentSchema = z.discriminatedUnion("component", [
  textComponent,
  textFieldComponent,
  choicePickerComponent,
  checkBoxComponent,
  columnComponent,
  rowComponent,
  buttonComponent,
]);

const answerValue = z.union([z.string().max(16 * 1024), z.boolean(), z.array(text).max(8)]);
const dataModelSchema = z
  .object({
    answers: z.record(fieldIdentifier, answerValue),
    requiredFieldIds: z.array(fieldIdentifier).max(8),
    ...identityContext,
  })
  .strict();
const createMessage = z
  .object({
    version: z.literal("v0.9"),
    createSurface: z
      .object({
        surfaceId: identifier,
        catalogId: z.literal(A2UI_CATALOG_ID),
        sendDataModel: z.literal(false),
      })
      .strict(),
  })
  .strict();
const dataMessage = z
  .object({
    version: z.literal("v0.9"),
    updateDataModel: z.object({ surfaceId: identifier, value: dataModelSchema }).strict(),
  })
  .strict();
const componentMessage = z
  .object({
    version: z.literal("v0.9"),
    updateComponents: z
      .object({ surfaceId: identifier, components: z.array(IntakeComponentSchema).max(32) })
      .strict(),
  })
  .strict();

export const A2uiSurfaceEventSchema = z
  .object({
    schemaVersion: z.literal("1.0"),
    sessionId: identifier,
    proposalId: identifier,
    proposalVersion: z.literal("1.0"),
    surfaceId: identifier,
    catalogId: z.literal(A2UI_CATALOG_ID),
    catalogVersion: z.literal("1.0"),
    protocolVersion: z.literal("0.9.1"),
    wireVersion: z.literal("v0.9"),
    messages: z.tuple([createMessage, dataMessage, componentMessage]),
  })
  .strict();

export type IntakeComponent = z.infer<typeof IntakeComponentSchema>;
export type A2uiSurfaceEvent = z.infer<typeof A2uiSurfaceEventSchema>;
export type IntakeAnswers = Record<string, string | boolean | string[]>;
export type IntakeField = {
  id: string;
  componentId: string;
  kind: "short_text" | "single_select" | "multi_select" | "boolean";
  label: string;
  description: string;
  required: boolean;
  choices: Array<{ label: string; value: string }>;
};

export type TrustedIntakeSurface = A2uiSurfaceEvent & {
  answers: IntakeAnswers;
  fields: IntakeField[];
  requiredFieldIds: string[];
};

export function parseA2uiSurfaceEvent(value: unknown): TrustedIntakeSurface {
  requireJsonSize(value);
  const result = A2uiSurfaceEventSchema.safeParse(value);
  if (!result.success) {
    const issue = result.error.issues[0];
    throw new Error(`Invalid A2UI intake surface${issue?.path.length ? ` at ${issue.path.join(".")}` : ""}: ${issue?.message ?? "unknown"}`);
  }
  return validateStructure(result.data);
}

export function isCurrentIntakeSurface(
  surface: TrustedIntakeSurface,
  state: { sessionId: string | null; status: string },
): boolean {
  return state.status === "awaiting_input" && state.sessionId === surface.sessionId;
}

function validateStructure(surface: A2uiSurfaceEvent): TrustedIntakeSurface {
  const [create, dataUpdate, componentUpdate] = surface.messages;
  const surfaceIds = [
    create.createSurface.surfaceId,
    dataUpdate.updateDataModel.surfaceId,
    componentUpdate.updateComponents.surfaceId,
  ];
  if (surfaceIds.some((id) => id !== surface.surfaceId)) {
    throw new Error("A2UI messages must target the declared surface.");
  }
  const data = dataUpdate.updateDataModel.value;
  if (
    data.sessionId !== surface.sessionId ||
    data.proposalId !== surface.proposalId ||
    data.proposalVersion !== surface.proposalVersion
  ) {
    throw new Error("A2UI proposal identity does not match its data model.");
  }
  if (new Set(data.requiredFieldIds).size !== data.requiredFieldIds.length) {
    throw new Error("A2UI required field IDs must be unique.");
  }
  const answerIds = Object.keys(data.answers);
  if (answerIds.length > 8 || data.requiredFieldIds.some((id) => !(id in data.answers))) {
    throw new Error("A2UI required fields must identify declared answers.");
  }

  const components = componentUpdate.updateComponents.components;
  const byId = new Map<string, IntakeComponent>();
  for (const component of components) {
    if (byId.has(component.id)) throw new Error("A2UI component IDs must be unique.");
    byId.set(component.id, component);
  }
  if (!byId.has("root")) throw new Error("A2UI surface requires a root component.");
  if (byId.get("root")?.component !== "Column") {
    throw new Error("A2UI surface root must use the trusted Column component.");
  }

  const reachable = new Set<string>();
  const visit = (id: string, path: ReadonlySet<string>, depth: number) => {
    if (depth > 4) throw new Error("A2UI component nesting exceeds the allowed depth.");
    if (path.has(id)) throw new Error("A2UI component graph contains a cycle.");
    const component = byId.get(id);
    if (!component) throw new Error("A2UI component graph references an unknown component.");
    reachable.add(id);
    const children = "children" in component ? component.children : "child" in component ? [component.child] : [];
    const nextPath = new Set(path).add(id);
    for (const child of children) visit(child, nextPath, depth + 1);
  };
  visit("root", new Set(), 1);
  if (reachable.size !== components.length) throw new Error("A2UI surface contains unreachable components.");

  const fields: IntakeField[] = [];
  const boundAnswers = new Set<string>();
  const actionNames: string[] = [];
  for (const component of components) {
    if (component.component === "Button") {
      const event = component.action.event;
      const context = event.context;
      if (
        context.sessionId !== surface.sessionId ||
        context.proposalId !== surface.proposalId ||
        context.proposalVersion !== surface.proposalVersion
      ) {
        throw new Error("A2UI action identity is stale or inconsistent.");
      }
      actionNames.push(event.name);
    }
    if (!(["TextField", "ChoicePicker", "CheckBox"] as const).includes(component.component as never)) continue;
    const input = component as z.infer<typeof textFieldComponent> | z.infer<typeof choicePickerComponent> | z.infer<typeof checkBoxComponent>;
    const fieldId = decodeBinding(input.value.path);
    if (input.id !== `field-${fieldId}`) {
      throw new Error("A2UI input identity must match its answer binding.");
    }
    if (!(fieldId in data.answers) || boundAnswers.has(fieldId)) {
      throw new Error("Every A2UI answer requires one unique input binding.");
    }
    boundAnswers.add(fieldId);
    const kind = input.component === "TextField" ? "short_text" : input.component === "CheckBox" ? "boolean" : input.variant === "mutuallyExclusive" ? "single_select" : "multi_select";
    fields.push({
      id: fieldId,
      componentId: input.id,
      kind,
      label: input.label,
      description: input.accessibility.description ?? "",
      required: data.requiredFieldIds.includes(fieldId),
      choices: input.component === "ChoicePicker" ? input.options : [],
    });
  }
  if (boundAnswers.size !== answerIds.length || answerIds.some((id) => !boundAnswers.has(id))) {
    throw new Error("Every A2UI answer requires one unique input binding.");
  }
  if (
    actionNames.length !== 2 ||
    actionNames.filter((name) => name === A2UI_SUBMIT_ACTION).length !== 1 ||
    actionNames.filter((name) => name === A2UI_SKIP_ACTION).length !== 1
  ) {
    throw new Error("A2UI intake requires exact submit and skip actions.");
  }
  validateInitialAnswers(fields, data.answers);
  return { ...surface, answers: structuredClone(data.answers), fields, requiredFieldIds: [...data.requiredFieldIds] };
}

function validateInitialAnswers(fields: IntakeField[], answers: IntakeAnswers): void {
  for (const field of fields) {
    const answer = answers[field.id];
    if (field.kind === "short_text" && typeof answer !== "string") throw new Error("A2UI text answer has an invalid value.");
    if (field.kind === "boolean" && typeof answer !== "boolean") throw new Error("A2UI boolean answer has an invalid value.");
    if ((field.kind === "single_select" || field.kind === "multi_select") && !Array.isArray(answer)) throw new Error("A2UI choice answer has an invalid value.");
    if (field.kind === "single_select" && Array.isArray(answer) && answer.length > 1) throw new Error("A2UI single-choice answer has too many values.");
    if (Array.isArray(answer) && answer.some((value) => !field.choices.some((choice) => choice.value === value))) throw new Error("A2UI choice answer is outside the declared options.");
  }
}

function decodeBinding(path: string): string {
  return path.slice("/answers/".length).replace(/~1/g, "/").replace(/~0/g, "~");
}

function requireJsonSize(value: unknown): void {
  let serialized: string | undefined;
  try {
    serialized = JSON.stringify(value);
  } catch {
    throw new Error("A2UI surface must be JSON-safe.");
  }
  if (serialized === undefined || new TextEncoder().encode(serialized).byteLength > MAX_A2UI_SURFACE_BYTES) {
    throw new Error("A2UI surface exceeds the allowed size.");
  }
}
