import {
  closestCorners,
  DndContext,
  DragOverlay,
  getFirstCollision,
  KeyboardSensor,
  PointerSensor,
  pointerWithin,
  rectIntersection,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import type {
  CollisionDetection,
  DragEndEvent,
  DragStartEvent,
  KeyboardCoordinateGetter,
} from "@dnd-kit/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import type { Kit, KitStatus } from "../api/types";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorBanner } from "../components/ui";
import { formatNumber } from "../lib/format";
import { ratingTooltip, statusLabel } from "../lib/labels";
import { usePresentationVersion } from "../lib/presentation";
import { kitStatusMutationOptions } from "../lib/kitStatusMutation";

// pointerWithin gives the most natural mouse-drag feel but only works for
// pointer sensors — keyboard drags need the rect-intersection fallback.
const collisionDetection: CollisionDetection = (args) => {
  const pointerCollisions = pointerWithin(args);
  return pointerCollisions.length > 0 ? pointerCollisions : rectIntersection(args);
};

// Keyboard drags jump one whole column per arrow press instead of the default
// 25px nudges (which the board's auto-scroll cancels out).
const columnKeyboardCoordinates: KeyboardCoordinateGetter = (event, { context }) => {
  const { active, droppableRects, droppableContainers, collisionRect } = context;
  if (!active || !collisionRect || !["ArrowLeft", "ArrowRight"].includes(event.code)) {
    return undefined;
  }
  event.preventDefault();

  const candidates = droppableContainers.getEnabled().filter((container) => {
    const rect = droppableRects.get(container.id);
    if (!rect) return false;
    return event.code === "ArrowRight"
      ? rect.left > collisionRect.left
      : rect.left < collisionRect.left;
  });

  const collisions = closestCorners({
    active,
    collisionRect,
    droppableRects,
    droppableContainers: candidates,
    pointerCoordinates: null,
  });
  const closestId = getFirstCollision(collisions, "id");
  if (closestId == null) return undefined;

  const target = droppableRects.get(closestId);
  return target ? { x: target.left + 16, y: target.top + 16 } : undefined;
};

type BoardView = "build" | "orders";

// Build view: what's on the bench. Orders view: what's in the mail, with
// everything already here rolled up into one "Received" column.
const BUILD_COLUMNS: readonly KitStatus[] = ["backlog", "building", "complete"];
const ORDER_COLUMNS: readonly KitStatus[] = ["pre_ordered", "ordered", "in_transit"];
const RECEIVED_ID = "received";
const RECEIVED_GROUP: ReadonlySet<KitStatus> = new Set(BUILD_COLUMNS);

const COLUMN_ACCENTS: Record<string, string> = {
  pre_ordered: "border-t-purple-400",
  ordered: "border-t-blue-400",
  in_transit: "border-t-amber-400",
  backlog: "border-t-teal-400", // inherited in_hand's teal in the merge
  building: "border-t-orange-400",
  complete: "border-t-green-500",
  [RECEIVED_ID]: "border-t-teal-400",
};

const VIEW_STORAGE_KEY = "plamotrack.boardView";

function initialView(): BoardView {
  const stored = localStorage.getItem(VIEW_STORAGE_KEY);
  return stored === "orders" ? "orders" : "build";
}

function KitCard({
  kit,
  isOverlay = false,
  showStatus = false,
}: {
  kit: Kit;
  isOverlay?: boolean;
  showStatus?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border border-zinc-200 bg-white p-3 text-sm ${
        isOverlay ? "rotate-2 shadow-xl ring-2 ring-indigo-400" : "shadow-sm"
      }`}
    >
      <div className="font-medium leading-snug">{kit.name}</div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500">
        <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-medium text-zinc-600">
          {kit.grade}
        </span>
        {kit.scale && <span>{kit.scale}</span>}
        {kit.kit_number && <span className="text-zinc-400">{kit.kit_number}</span>}
        {showStatus && <StatusBadge status={kit.status} />}
      </div>
      {kit.rating != null && (
        <div className="mt-1 text-xs text-amber-500" title={ratingTooltip(kit.rating)}>
          {"★".repeat(kit.rating)}
          <span className="text-zinc-300">{"★".repeat(5 - kit.rating)}</span>
        </div>
      )}
    </div>
  );
}

function DraggableCard({ kit, showStatus = false }: { kit: Kit; showStatus?: boolean }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: kit.id });
  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      className={`cursor-grab touch-none active:cursor-grabbing ${isDragging ? "opacity-30" : ""}`}
    >
      <KitCard kit={kit} showStatus={showStatus} />
    </div>
  );
}

function Column({
  id,
  title,
  kits,
  showStatus = false,
}: {
  id: string;
  title: string;
  kits: Kit[];
  showStatus?: boolean;
}) {
  const { t } = useTranslation();
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <div className="flex w-full min-w-56 max-w-80 shrink-0 flex-col">
      <div
        className={`rounded-t-lg border-t-4 bg-white px-3 py-2 ${COLUMN_ACCENTS[id]} border-x border-zinc-200`}
      >
        <span className="text-sm font-semibold">{title}</span>
        <span
          className="ms-2 rounded-full bg-zinc-100 px-1.5 text-xs text-zinc-500"
          data-testid={`column-count-${id}`}
        >
          {formatNumber(kits.length)}
        </span>
      </div>
      <div
        ref={setNodeRef}
        className={`flex-1 space-y-2 rounded-b-lg border border-t-0 border-zinc-200 p-2 transition-colors ${
          isOver ? "bg-indigo-50 ring-2 ring-inset ring-indigo-300" : "bg-zinc-50"
        }`}
        style={{ minHeight: "8rem" }}
      >
        {kits.map((kit) => (
          <DraggableCard key={kit.id} kit={kit} showStatus={showStatus} />
        ))}
        {kits.length === 0 && (
          <div className="px-2 py-6 text-center text-xs text-zinc-400">
            {isOver ? t("board.dropHere") : "—"}
          </div>
        )}
      </div>
    </div>
  );
}

export function BoardPage() {
  const { t } = useTranslation();
  // Column counts and rating tooltips render through the instance's formatting
  // locale, so this subtree has to hear a settings change that isn't also a
  // language change — `useTranslation` only re-renders on `languageChanged`,
  // and the Outlet element identity keeps a Layout render from reaching here
  // (#177 review, P3-1; the same trap as #174's P3-1).
  usePresentationVersion();
  const queryClient = useQueryClient();
  const [view, setView] = useState<BoardView>(initialView);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: kits,
    isLoading,
    isError,
    error,
  } = useQuery({ queryKey: ["kits"], queryFn: () => api.listKits() });

  const selectView = (next: BoardView) => {
    setView(next);
    localStorage.setItem(VIEW_STORAGE_KEY, next);
  };

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: columnKeyboardCoordinates }),
  );

  const statusMutation = useMutation(kitStatusMutationOptions(queryClient, setActionError));

  const byStatus = useMemo(() => {
    const groups = new Map<KitStatus, Kit[]>(
      (["pre_ordered", "ordered", "in_transit", "backlog", "building", "complete"] as const).map(
        (status) => [status, []],
      ),
    );
    for (const kit of kits ?? []) {
      groups.get(kit.status)?.push(kit);
    }
    // Most recently moved first within each column.
    for (const group of groups.values()) {
      group.sort((a, b) => b.status_updated_at.localeCompare(a.status_updated_at));
    }
    return groups;
  }, [kits]);

  const receivedKits = useMemo(
    () =>
      [...RECEIVED_GROUP]
        .flatMap((status) => byStatus.get(status) ?? [])
        .sort((a, b) => b.status_updated_at.localeCompare(a.status_updated_at)),
    [byStatus],
  );

  const activeKit = activeId ? (kits ?? []).find((kit) => kit.id === activeId) : null;

  const onDragStart = (event: DragStartEvent) => {
    setActionError(null);
    setActiveId(String(event.active.id));
  };

  const onDragEnd = (event: DragEndEvent) => {
    setActiveId(null);
    const { active, over } = event;
    if (!over) return;
    const kit = (kits ?? []).find((k) => k.id === active.id);
    if (!kit) return;

    // Dropping on the aggregate "Received" column means "it's here" — which is
    // backlog unless the kit is already past that point.
    const target: KitStatus | null =
      over.id === RECEIVED_ID
        ? RECEIVED_GROUP.has(kit.status)
          ? null
          : "backlog"
        : (over.id as KitStatus);
    if (target && kit.status !== target) {
      statusMutation.mutate({ id: kit.id, status: target });
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">
          {view === "build" ? t("board.buildPipeline") : t("board.ordersPipeline")}
        </h1>
        <div className="flex items-center gap-3">
          <span className="hidden text-sm text-zinc-500 sm:inline">{t("board.dragHint")}</span>
          <div className="flex rounded-lg border border-zinc-300 bg-white p-0.5">
            {(["build", "orders"] as const).map((option) => (
              <button
                key={option}
                onClick={() => selectView(option)}
                className={`rounded-md px-3 py-1 text-sm font-medium ${
                  view === option
                    ? "bg-indigo-600 text-white"
                    : "text-zinc-600 hover:text-zinc-900"
                }`}
              >
                {option === "build" ? t("board.buildView") : t("board.ordersView")}
              </button>
            ))}
          </div>
        </div>
      </div>

      <ErrorBanner message={actionError} />

      {isError ? (
        <ErrorBanner message={t("board.loadFailed", { message: (error as Error).message })} />
      ) : isLoading ? (
        <EmptyState>{t("common.loading")}</EmptyState>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={collisionDetection}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
          onDragCancel={() => setActiveId(null)}
        >
          <div className="flex gap-3 overflow-x-auto pb-4">
            {view === "build" ? (
              BUILD_COLUMNS.map((status) => (
                <Column
                  key={status}
                  id={status}
                  title={statusLabel(status)}
                  kits={byStatus.get(status) ?? []}
                />
              ))
            ) : (
              <>
                {ORDER_COLUMNS.map((status) => (
                  <Column
                    key={status}
                    id={status}
                    title={statusLabel(status)}
                    kits={byStatus.get(status) ?? []}
                  />
                ))}
                <Column id={RECEIVED_ID} title={t("board.received")} kits={receivedKits} showStatus />
              </>
            )}
          </div>
          <DragOverlay>
            {activeKit ? <KitCard kit={activeKit} isOverlay showStatus={view === "orders"} /> : null}
          </DragOverlay>
        </DndContext>
      )}
    </div>
  );
}
