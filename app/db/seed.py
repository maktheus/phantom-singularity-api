import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Concurso, Question, Difficulty

# Use sync driver for seeding
DATABASE_URL = "postgresql://phantom:phantom@db:5432/phantom"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def seed():
    db = SessionLocal()
    try:
        # Check if already seeded
        if db.query(Concurso).first():
            print("Database already has data. Skipping seed.")
            return

        print("Seeding concursos...")
        c1 = Concurso(
            id=uuid.uuid4(), slug='policial', name='Carreira Policial',
            area='Segurança', emoji='👮', color_hex='#3B82F6'
        )
        c2 = Concurso(
            id=uuid.uuid4(), slug='tributario', name='Área Fiscal',
            area='Tributária', emoji='💰', color_hex='#FBBF24'
        )
        c3 = Concurso(
            id=uuid.uuid4(), slug='judiciario', name='Poder Judiciário',
            area='Judiciária', emoji='⚖️', color_hex='#A78BFA'
        )
        c4 = Concurso(
            id=uuid.uuid4(), slug='administrativo', name='Administrativo',
            area='Geral', emoji='📋', color_hex='#34D399'
        )
        c5 = Concurso(
            id=uuid.uuid4(), slug='ti', name='Tecnologia da Informação',
            area='TI', emoji='💻', color_hex='#06B6D4'
        )
        c6 = Concurso(
            id=uuid.uuid4(), slug='mixed', name='Geral / Misto',
            area='Geral', emoji='🎲', color_hex='#F87171'
        )
        
        db.add_all([c1, c2, c3, c4, c5, c6])
        db.flush() # get IDs

        print("Seeding sample questions...")
        q1 = Question(
            id=uuid.uuid4(), concurso_id=c1.id,
            text="De acordo com a CF/88, a segurança pública, dever do Estado, direito e responsabilidade de todos, é exercida para a preservação da ordem pública e da incolumidade das pessoas e do patrimônio, através dos seguintes órgãos, EXCETO:",
            options=[
                {"index": 0, "text": "Polícia Federal", "tip": "PF é órgão de segurança pública (Art. 144, I)"},
                {"index": 1, "text": "Polícia Civil", "tip": "PC é órgão de segurança pública (Art. 144, IV)"},
                {"index": 2, "text": "Guarda Municipal", "tip": "Embora mencionada no Art. 144, § 8º, as guardas não são tratadas no caput como 'órgãos de segurança pública' clássicos em muitas questões de concurso (embora o STF tenha entendimento recente ampliando isso, a questão clássica foca no caput)"},
                {"index": 3, "text": "Forças Armadas", "tip": "Correto! As Forças Armadas (Marinha, Exército e Aeronáutica) pertencem ao capítulo da Defesa do Estado, não da Segurança Pública."}
            ],
            correct_index=3,
            topic="Segurança Pública",
            difficulty=Difficulty.easy,
            source="real"
        )
        db.add(q1)
        
        db.commit()
        print("Seed completed successfully!")
    except Exception as e:
        db.rollback()
        print(f"Error seeding: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed()
