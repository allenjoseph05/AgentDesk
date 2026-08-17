import {
  basicCatalog,
  MessageProcessor,
  type A2uiMessage,
  type ReactComponentImplementation,
  type SurfaceModel,
} from "./compatibility.ts";

export const FIXTURE_SURFACE_ID = "research-summary-spike";

export const fixtureMessages: A2uiMessage[] = [
  {
    version: "v0.9.1",
    createSurface: {
      surfaceId: FIXTURE_SURFACE_ID,
      catalogId: basicCatalog.id,
    },
  },
  {
    version: "v0.9.1",
    updateComponents: {
      surfaceId: FIXTURE_SURFACE_ID,
      components: [
        {
          id: "root",
          component: "Card",
          child: "content",
        },
        {
          id: "content",
          component: "Column",
          children: ["label", "summary"],
        },
        {
          id: "label",
          component: "Text",
          text: "A2UI research summary",
        },
        {
          id: "summary",
          component: "Text",
          text: { path: "/summary" },
        },
      ],
    },
  },
  {
    version: "v0.9.1",
    updateDataModel: {
      surfaceId: FIXTURE_SURFACE_ID,
      path: "/",
      value: { summary: "Fixture surface ready." },
    },
  },
];

export type FixtureProcessor = MessageProcessor<ReactComponentImplementation>;
export type FixtureSurface = SurfaceModel<ReactComponentImplementation>;

export interface FixtureRuntime {
  processor: FixtureProcessor;
  surface: FixtureSurface;
}

export function processTrustedMessages(
  processor: FixtureProcessor,
  messages: A2uiMessage[],
): void {
  for (const message of messages) {
    if (!("updateComponents" in message)) {
      continue;
    }
    for (const component of message.updateComponents.components) {
      if (component.component && !basicCatalog.components.has(component.component)) {
        throw new Error(`Unknown A2UI component rejected: ${component.component}`);
      }
    }
  }
  processor.processMessages(messages);
}

export function createFixtureRuntime(): FixtureRuntime {
  const processor = new MessageProcessor([basicCatalog], undefined, { version: "v0.9.1" });
  processTrustedMessages(processor, fixtureMessages);
  const surface = processor.model.getSurface(FIXTURE_SURFACE_ID);
  if (surface === undefined) {
    throw new Error("A2UI fixture surface was not created");
  }
  return { processor, surface };
}

export function updateFixtureSummary(processor: FixtureProcessor, summary: string): void {
  processTrustedMessages(processor, [
    {
      version: "v0.9.1",
      updateDataModel: {
        surfaceId: FIXTURE_SURFACE_ID,
        path: "/summary",
        value: summary,
      },
    },
  ]);
}
