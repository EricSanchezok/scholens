import { LoadingState } from "@/components/feedback";

export default function RouteLoading() {
  return (
    <main className="bg-canvas grid min-h-dvh place-items-center px-4">
      <div className="w-full max-w-xl">
        <LoadingState />
      </div>
    </main>
  );
}
