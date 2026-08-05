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

import { api, ApiError } from "../api/client";
import type { Kit, KitStatus } from "../api/types";
import { KIT_STATUSES } from "../api/types";
import { EmptyState, ErrorBanner } from "../components/ui";
import { STATUS_LABELS } from "../lib/format";

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

const COLUMN_ACCENTS: Record<KitStatus, string> = {
  backlog: "border-t-zinc-400",
  pre_ordered: "border-t-purple-400",
  ordered: "border-t-blue-400",
  in_transit: "border-t-amber-400",
  in_hand: "border-t-teal-400",
  building: "border-t-orange-400",
  complete: "border-t-green-500",
};

function KitCard({ kit, isOverlay = false }: { kit: Kit; isOverlay?: boolean }) {
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
      </div>
      {kit.rating != null && (
        <div className="mt-1 text-xs text-amber-500" title={`${kit.rating}/5`}>
          {"★".repeat(kit.rating)}
          <span className="text-zinc-300">{"★".repeat(5 - kit.rating)}</span>
        </div>
      )}
    </div>
  );
}

function DraggableCard({ kit }: { kit: Kit }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: kit.id });
  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      className={`cursor-grab touch-none active:cursor-grabbing ${isDragging ? "opacity-30" : ""}`}
    >
      <KitCard kit={kit} />
    </div>
  );
}

function Column({ status, kits }: { status: KitStatus; kits: Kit[] }) {
  const { setNodeRef, isOver } = useDroppable({ id: status });
  return (
    <div className="flex w-60 shrink-0 flex-col">
      <div
        className={`rounded-t-lg border-t-4 bg-white px-3 py-2 ${COLUMN_ACCENTS[status]} border-x border-zinc-200`}
      >
        <span className="text-sm font-semibold">{STATUS_LABELS[status]}</span>
        <span className="ml-2 rounded-full bg-zinc-100 px-1.5 text-xs text-zinc-500">
          {kits.length}
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
          <DraggableCard key={kit.id} kit={kit} />
        ))}
        {kits.length === 0 && (
          <div className="px-2 py-6 text-center text-xs text-zinc-400">
            {isOver ? "Drop here" : "—"}
          </div>
        )}
      </div>
    </div>
  );
}

export function BoardPage() {
  const queryClient = useQueryClient();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: kits,
    isLoading,
    isError,
    error,
  } = useQuery({ queryKey: ["kits"], queryFn: () => api.listKits() });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: columnKeyboardCoordinates }),
  );

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: KitStatus }) =>
      api.updateKit(id, { status }),
    // Optimistic: the card lands in its new column immediately; rolled back on error.
    onMutate: async ({ id, status }) => {
      await queryClient.cancelQueries({ queryKey: ["kits"] });
      const previous = queryClient.getQueryData<Kit[]>(["kits"]);
      queryClient.setQueryData<Kit[]>(["kits"], (current) =>
        (current ?? []).map((kit) =>
          kit.id === id
            ? { ...kit, status, status_updated_at: new Date().toISOString() }
            : kit,
        ),
      );
      return { previous };
    },
    onError: (err, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(["kits"], context.previous);
      setActionError(err instanceof ApiError ? err.message : "Move failed");
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["kits"] }),
  });

  const byStatus = useMemo(() => {
    const groups = new Map<KitStatus, Kit[]>(KIT_STATUSES.map((status) => [status, []]));
    for (const kit of kits ?? []) {
      groups.get(kit.status)?.push(kit);
    }
    // Most recently moved first within each column.
    for (const group of groups.values()) {
      group.sort((a, b) => b.status_updated_at.localeCompare(a.status_updated_at));
    }
    return groups;
  }, [kits]);

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
    const target = over.id as KitStatus;
    if (kit && kit.status !== target) {
      statusMutation.mutate({ id: kit.id, status: target });
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Build Pipeline</h1>
        <span className="text-sm text-zinc-500">
          {kits?.length ?? 0} kit{(kits?.length ?? 0) === 1 ? "" : "s"} — drag cards to update
          status
        </span>
      </div>

      <ErrorBanner message={actionError} />

      {isError ? (
        <ErrorBanner message={`Failed to load kits: ${(error as Error).message}`} />
      ) : isLoading ? (
        <EmptyState>Loading…</EmptyState>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={collisionDetection}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
          onDragCancel={() => setActiveId(null)}
        >
          <div className="flex gap-3 overflow-x-auto pb-4">
            {KIT_STATUSES.map((status) => (
              <Column key={status} status={status} kits={byStatus.get(status) ?? []} />
            ))}
          </div>
          <DragOverlay>{activeKit ? <KitCard kit={activeKit} isOverlay /> : null}</DragOverlay>
        </DndContext>
      )}
    </div>
  );
}
