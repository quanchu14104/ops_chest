import InboxPanel from "../components/InboxPanel";
import Chat from "./Chat";

// Màn hình chính: chat là cửa vào (kèm bản tin đầu ngày), hộp đề xuất luôn nằm bên cạnh để duyệt ngay.
export default function Home() {
  return (
    <div className="home">
      <Chat home />
      <InboxPanel />
    </div>
  );
}
