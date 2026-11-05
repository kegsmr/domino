import { useState } from "react";


export default function Counter() {
  const [count, setCount] = useState(0);

  return (
    <div>
      <button id="inc" onClick={() => setCount(count + 1)}>+1</button>
      <span id="count">{count}</span>
    </div>
  );
}
