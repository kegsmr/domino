import { createRoot } from "react-dom/client";

import Chat from "./Chat.jsx";
import Counter from "./Counter.jsx";
import Todo from "./Todo.jsx";


const pages = { "/counter": Counter, "/todo": Todo, "/chat": Chat };
const Page = pages[location.pathname] ?? (() => <p>Not found</p>);

createRoot(document.getElementById("root")).render(<Page />);
