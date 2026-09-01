import { BoardDashboardScreen } from "../../../../../components/screens/full-ui-workflows";

type PageProps = {
  params: Promise<{ productionId: string; boardId: string }>;
};

export default async function BoardPage({ params }: PageProps) {
  const { productionId, boardId } = await params;
  return <BoardDashboardScreen productionId={productionId} boardId={boardId} />;
}
