import type { ReactComponentImplementation } from "@a2ui/react/v0_9";
import { ComponentContext, MessageProcessor, type SurfaceModel } from "@a2ui/web_core/v0_9";
import {
  Component,
  type ErrorInfo,
  type ReactNode,
  useMemo,
  useRef,
  useState,
} from "react";

import { agentDeskA2uiCatalog, IntakeRenderProvider } from "./catalog";
import {
  A2UI_SKIP_ACTION,
  A2UI_SUBMIT_ACTION,
  type IntakeAnswers,
  type IntakeField,
  type TrustedIntakeSurface,
} from "./contracts";

export interface TrustedA2uiIntakeProps {
  busy?: boolean;
  onSkip(surface: TrustedIntakeSurface): unknown | Promise<unknown>;
  onSubmit(surface: TrustedIntakeSurface, answers: IntakeAnswers): unknown | Promise<unknown>;
  surface: TrustedIntakeSurface;
}

type ActionHandler = (name: string) => void;
type BuiltSurface =
  | { model: SurfaceModel<ReactComponentImplementation> }
  | { error: Error };

export function TrustedA2uiIntake({
  busy = false,
  onSkip,
  onSubmit,
  surface,
}: TrustedA2uiIntakeProps) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const handlerRef = useRef<ActionHandler>(() => undefined);
  const built = useMemo<BuiltSurface>(() => {
    try {
      return { model: buildA2uiSurfaceModel(surface, (name) => handlerRef.current(name)) } as const;
    } catch (error) {
      return { error: error instanceof Error ? error : new Error("A2UI processing failed.") } as const;
    }
  }, [surface]);

  handlerRef.current = (name) => {
    if (busy) return;
    if (name === A2UI_SKIP_ACTION) {
      setErrors({});
      void onSkip(surface);
      return;
    }
    if (name !== A2UI_SUBMIT_ACTION || !("model" in built) || built.model === undefined) return;
    const current = built.model.dataModel.get("/answers") as unknown;
    const result = normalizeIntakeAnswers(surface.fields, current);
    setErrors(result.errors);
    if (Object.keys(result.errors).length === 0) void onSubmit(surface, result.answers);
  };

  const fallback = (
    <StaticIntakeForm
      busy={busy}
      onSkip={() => onSkip(surface)}
      onSubmit={(answers) => onSubmit(surface, answers)}
      surface={surface}
    />
  );
  if (!("model" in built) || built.model === undefined) return fallback;

  return (
    <section className="a2ui-intake" aria-label="Clarify research scope" data-a2ui-catalog={surface.catalogId}>
      <IntakeRenderProvider busy={busy} errors={errors} requiredFieldIds={surface.requiredFieldIds}>
        <IntakeRenderBoundary fallback={fallback} resetKey={`${surface.sessionId}:${surface.proposalId}`}>
          <TrustedSurfaceTree id="root" surface={built.model} />
        </IntakeRenderBoundary>
      </IntakeRenderProvider>
    </section>
  );
}

function TrustedSurfaceTree({
  id,
  surface,
}: {
  id: string;
  surface: SurfaceModel<ReactComponentImplementation>;
}) {
  const componentModel = surface.componentsModel.get(id);
  if (componentModel === undefined) throw new Error(`Trusted A2UI component is missing: ${id}`);
  const implementation = surface.catalog.components.get(componentModel.type);
  if (implementation === undefined) throw new Error(`Trusted A2UI component is unknown: ${componentModel.type}`);
  const context = useMemo(() => new ComponentContext(surface, id), [id, surface]);
  const buildChild = (childId: string) => (
    <TrustedSurfaceTree id={childId} key={childId} surface={surface} />
  );
  const RenderComponent = implementation.render;
  return <RenderComponent buildChild={buildChild} context={context} />;
}

export function buildA2uiSurfaceModel(
  surface: TrustedIntakeSurface,
  onAction: ActionHandler,
): SurfaceModel<ReactComponentImplementation> {
  const processor = new MessageProcessor(
    [agentDeskA2uiCatalog],
    (action) => {
      if (action.surfaceId !== surface.surfaceId || action.sourceComponentId === "") return;
      if (action.name === A2UI_SUBMIT_ACTION || action.name === A2UI_SKIP_ACTION) {
        onAction(action.name);
      }
    },
    { version: "v0.9" },
  );
  processor.processMessages(surface.messages);
  const model = processor.model.getSurface(surface.surfaceId);
  if (model === undefined || model.catalog.id !== surface.catalogId) {
    throw new Error("The trusted A2UI processor did not create the expected surface.");
  }
  return model;
}

export function normalizeIntakeAnswers(
  fields: IntakeField[],
  value: unknown,
): { answers: IntakeAnswers; errors: Record<string, string> } {
  const input = typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
  const answers: IntakeAnswers = {};
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const raw = input[field.id];
    if (field.kind === "boolean") {
      if (typeof raw === "boolean") answers[field.id] = raw;
      else errors[field.id] = `${field.label} has an invalid value.`;
      continue;
    }
    if (field.kind === "short_text") {
      const normalized = typeof raw === "string" ? raw.trim() : "";
      if (normalized) answers[field.id] = normalized;
      else if (field.required) errors[field.id] = `${field.label} is required.`;
      continue;
    }
    const selected = Array.isArray(raw)
      ? raw.filter((item): item is string => typeof item === "string")
      : [];
    const allowed = new Set(field.choices.map((choice) => choice.value));
    if (selected.length !== new Set(selected).size || selected.some((item) => !allowed.has(item))) {
      errors[field.id] = `${field.label} contains an invalid selection.`;
      continue;
    }
    if (field.required && selected.length === 0) {
      errors[field.id] = `${field.label} is required.`;
      continue;
    }
    if (field.kind === "single_select") {
      if (selected.length > 1) errors[field.id] = `${field.label} allows only one selection.`;
      else if (selected[0] !== undefined) answers[field.id] = selected[0];
    } else if (selected.length > 0) {
      answers[field.id] = selected;
    }
  }
  return { answers, errors };
}

export function StaticIntakeForm({
  busy = false,
  onSkip,
  onSubmit,
  surface,
}: {
  busy?: boolean;
  onSkip(): unknown | Promise<unknown>;
  onSubmit(answers: IntakeAnswers): unknown | Promise<unknown>;
  surface: TrustedIntakeSurface;
}) {
  const [answers, setAnswers] = useState<IntakeAnswers>(() => structuredClone(surface.answers));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const submit = () => {
    const result = normalizeIntakeAnswers(surface.fields, answers);
    setErrors(result.errors);
    if (Object.keys(result.errors).length === 0) void onSubmit(result.answers);
  };
  return (
    <section className="a2ui-intake a2ui-intake--fallback" aria-label="Clarify research scope" data-renderer="static-fallback">
      <h3>Clarify your decision</h3>
      <p>Answer a few bounded questions before research begins.</p>
      {surface.fields.map((field) => (
        <FallbackField
          answers={answers}
          busy={busy}
          error={errors[field.id]}
          field={field}
          key={field.id}
          setAnswer={(answer) => setAnswers((current) => ({ ...current, [field.id]: answer }))}
        />
      ))}
      <div className="a2ui-intake__actions">
        <button className="a2ui-intake__button a2ui-intake__button--primary" disabled={busy} onClick={submit} type="button">
          Continue
        </button>
        <button className="a2ui-intake__button a2ui-intake__button--borderless" disabled={busy} onClick={() => void onSkip()} type="button">
          Skip clarification
        </button>
      </div>
    </section>
  );
}

function FallbackField({
  answers,
  busy,
  error,
  field,
  setAnswer,
}: {
  answers: IntakeAnswers;
  busy: boolean;
  error?: string;
  field: IntakeField;
  setAnswer(value: string | boolean | string[]): void;
}) {
  const id = useMemo(() => `fallback-${field.componentId}`, [field.componentId]);
  const descriptionId = `${id}-description`;
  const errorId = `${id}-error`;
  const describedBy = [field.description ? descriptionId : "", error ? errorId : ""].filter(Boolean).join(" ") || undefined;
  if (field.kind === "short_text") {
    return (
      <div className="a2ui-intake__field">
        <label htmlFor={id}>{field.label}</label>
        {field.description && <span id={descriptionId} className="a2ui-intake__description">{field.description}</span>}
        <input aria-describedby={describedBy} aria-invalid={error ? true : undefined} disabled={busy} id={id} onChange={(event) => setAnswer(event.target.value)} required={field.required} value={stringAnswer(answers[field.id])} />
        {error && <span id={errorId} className="a2ui-intake__error">{error}</span>}
      </div>
    );
  }
  if (field.kind === "boolean") {
    return (
      <div className="a2ui-intake__field a2ui-intake__checkbox">
        <label htmlFor={id}><input checked={Boolean(answers[field.id])} disabled={busy} id={id} onChange={(event) => setAnswer(event.target.checked)} type="checkbox" /> <span>{field.label}</span></label>
        {field.description && <span id={descriptionId} className="a2ui-intake__description">{field.description}</span>}
      </div>
    );
  }
  const selected = Array.isArray(answers[field.id]) ? (answers[field.id] as string[]) : [];
  const multiple = field.kind === "multi_select";
  return (
    <fieldset aria-describedby={describedBy} aria-invalid={error ? true : undefined} className="a2ui-intake__field">
      <legend>{field.label}</legend>
      {field.description && <span id={descriptionId} className="a2ui-intake__description">{field.description}</span>}
      <div className="a2ui-intake__choices">
        {field.choices.map((choice) => <label key={choice.value}><input checked={selected.includes(choice.value)} disabled={busy} name={field.id} onChange={() => setAnswer(multiple ? selected.includes(choice.value) ? selected.filter((value) => value !== choice.value) : [...selected, choice.value] : [choice.value])} type={multiple ? "checkbox" : "radio"} value={choice.value} /> <span>{choice.label}</span></label>)}
      </div>
      {error && <span id={errorId} className="a2ui-intake__error">{error}</span>}
    </fieldset>
  );
}

class IntakeRenderBoundary extends Component<
  { children: ReactNode; fallback: ReactNode; resetKey: string },
  { failed: boolean; resetKey: string }
> {
  state = { failed: false, resetKey: this.props.resetKey };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  static getDerivedStateFromProps(props: { resetKey: string }, state: { resetKey: string }) {
    return props.resetKey === state.resetKey ? null : { failed: false, resetKey: props.resetKey };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Trusted A2UI renderer fell back to the local intake form.", error, info);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function stringAnswer(value: string | boolean | string[] | undefined): string {
  return typeof value === "string" ? value : "";
}
