import { memo, useCallback, useEffect, useState } from "react";


const Item = memo(function Item({ item, onToggle }) {
  return (
    <li className={item.done ? "done" : undefined}>
      <input type="checkbox" checked={item.done} onChange={() => onToggle(item)} /> {item.text}
    </li>
  );
});


export default function Todo() {
  const [items, setItems] = useState(null);
  const [text, setText] = useState("");

  useEffect(() => {
    fetch("/api/todos").then((response) => response.json()).then(setItems);
  }, []);

  // Optimistic: shown at once, sent to the server, put back if the server refuses
  const toggle = useCallback((item) => {
    const flip = (done) => setItems((items) => items.map((i) => (i.id === item.id ? { ...i, done } : i)));
    flip(!item.done);
    fetch(`/api/todos/${item.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ done: !item.done }),
    }).then((response) => response.ok || flip(item.done), () => flip(item.done));
  }, []);

  async function add(event) {
    event.preventDefault();
    if (!text.trim()) return;
    const response = await fetch("/api/todos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text.trim() }),
    });
    const item = await response.json();
    setItems((items) => [...items, item]);
    setText("");
  }

  if (items === null) return <p>Loading…</p>;

  return (
    <div>
      <form onSubmit={add}>
        <input id="new" value={text} onChange={(event) => setText(event.target.value)}
          placeholder="What needs doing?" autoComplete="off" />
        <button id="add" type="submit">Add</button>
      </form>
      <p id="summary">{items.filter((item) => item.done).length} of {items.length} done</p>
      <ul id="todos">
        {items.map((item) => <Item key={item.id} item={item} onToggle={toggle} />)}
      </ul>
    </div>
  );
}
