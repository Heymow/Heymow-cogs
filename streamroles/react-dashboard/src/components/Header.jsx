import './Header.css'

function Header({ onHelpClick }) {
  return (
    <header className="header">
      <h1>🌿 SoundGarden Stream Stats</h1>
      <p className="subtitle">Community Streaming Analytics</p>
      <button className="help-button" onClick={onHelpClick} title="Help">
        ?
      </button>
    </header>
  )
}

export default Header
