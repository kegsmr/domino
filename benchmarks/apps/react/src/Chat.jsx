import { useEffect, useRef, useState } from "react";


export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const socket = useRef(null);

  useEffect(() => {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/chat`);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setMessages((messages) => (data.history ?? [...messages, data.message]).slice(-50));
    };
    socket.current = ws;
    return () => ws.close();
  }, []);

  function send(event) {
    event.preventDefault();
    if (!text.trim()) return;
    socket.current.send(JSON.stringify({ name: "me", text: text.trim() }));
    setText("");
  }

  return (
    <div>
      <ul id="messages">
        {messages.map((message) => (
          <li key={message.id}><strong>{message.name}</strong> {message.text}</li>
        ))}
      </ul>
      <form onSubmit={send}>
        <input id="text" value={text} onChange={(event) => setText(event.target.value)}
          placeholder="Message" autoComplete="off" />
        <button id="send" type="submit">Send</button>
      </form>
    </div>
  );
}
